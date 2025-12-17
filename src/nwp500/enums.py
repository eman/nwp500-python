"""Enumerations for Navien device protocol.

This module contains enumerations for the Navien device protocol. These
enums define valid values for device control commands, status fields, and
capabilities.
"""

from enum import IntEnum

# ============================================================================
# Status Value Enumerations
# ============================================================================


class OnOffFlag(IntEnum):
    """Generic on/off flag used throughout status fields.

    Used for: Power status, TOU status, recirculation status, vacation mode,
    anti-legionella, and many other boolean device settings.
    """

    OFF = 1
    ON = 2


class Operation(IntEnum):
    """Device operation state."""

    UNKNOWN = 0
    OPERATION = 1
    STOP = 2


class DhwOperationSetting(IntEnum):
    """DHW operation setting modes (user-configured heating preferences).

    This enum represents the user's configured mode preference - what
    heating mode the device should use when it needs to heat water. These
    values appear in the dhw_operation_setting field and are set via user
    commands.
    """

    HEAT_PUMP = 1  # Heat Pump Only - most efficient, slowest recovery
    ELECTRIC = 2  # Electric Only - least efficient, fastest recovery
    ENERGY_SAVER = 3  # Hybrid: Efficiency - balanced, good default
    HIGH_DEMAND = 4  # Hybrid: Boost - maximum heating capacity
    VACATION = 5  # Vacation mode - suspends heating to save energy
    POWER_OFF = 6  # Device powered off


class CurrentOperationMode(IntEnum):
    """Current operation mode (real-time operational state).

    This enum represents the device's current actual operational state - what
    the device is doing RIGHT NOW. These values appear in the operation_mode
    field and change automatically based on heating demand.
    """

    STANDBY = 0  # Device is idle, not actively heating
    HEAT_PUMP_MODE = 32  # Heat pump is actively running to heat water
    HYBRID_EFFICIENCY_MODE = 64  # Device actively heating in Energy Saver mode
    HYBRID_BOOST_MODE = 96  # Device actively heating in High Demand mode


class HeatSource(IntEnum):
    """Currently active heat source (read-only status).

    This reflects what the device is currently using, not what mode
    it's set to. In Hybrid mode, this field shows which source(s)
    are active at any given moment.
    """

    UNKNOWN = 0
    HEATPUMP = 1
    HEATELEMENT = 2
    HEATPUMP_HEATELEMENT = 3


class DREvent(IntEnum):
    """Demand Response event status.

    Allows utilities to manage grid load by signaling water heaters
    to reduce consumption (shed) or pre-heat (load up) before peak periods.
    """

    UNKNOWN = 0  # Not Applied
    RUN_NORMAL = 1  # Normal operation during DR event
    SHED = 2  # Load shedding - reduce power
    LOADUP = 3  # Pre-heat before expected high demand
    LOADUP_ADV = 4  # Advanced load-up strategy
    CPE = 5  # Customer peak event / Grid emergency


class WaterLevel(IntEnum):
    """Hot water level indicator (displayed as gauge in app).

    Note: IDs are non-sequential, likely represent bit positions
    for multi-level displays.
    """

    LOW = 2
    LOW_MEDIUM = 8
    MEDIUM_HIGH = 16
    HIGH = 4


class FilterChange(IntEnum):
    """Air filter status for heat pump models."""

    NORMAL = 0
    REPLACE_NEED = 1
    UNKNOWN = 2


class RecirculationMode(IntEnum):
    """Recirculation pump operation mode."""

    UNKNOWN = 0
    ALWAYS = 1  # Pump always runs
    BUTTON = 2  # Manual activation only
    SCHEDULE = 3  # Runs on configured schedule
    TEMPERATURE = 4  # Activates when pipe temp drops


# ============================================================================
# Time of Use (TOU) Enumerations
# ============================================================================


class TouWeekType(IntEnum):
    """Day grouping for TOU schedules.

    TOU schedules can be configured separately for weekdays and weekends
    to account for different electricity rates and usage patterns.
    """

    WEEK_DAY = 0  # Monday through Friday
    WEEK_END = 1  # Saturday and Sunday


class TouRateType(IntEnum):
    """Electricity rate period type.

    Device behavior during each rate period can be configured.
    Typically, devices heat aggressively during off-peak, maintain
    temperature during mid-peak, and avoid heating during on-peak
    unless necessary.
    """

    UNKNOWN = 0
    OFF_PEAK = 1  # Lowest rates - heat aggressively
    MID_PEAK = 2  # Medium rates - heat normally
    ON_PEAK = 3  # Highest rates - minimize heating


# ============================================================================
# Temperature and Unit Enumerations
# ============================================================================


class TemperatureType(IntEnum):
    """Temperature display unit preference."""

    CELSIUS = 1
    FAHRENHEIT = 2


class TempFormulaType(IntEnum):
    """Temperature conversion formula type.

    Different device models use slightly different rounding algorithms
    when converting internal Celsius values to Fahrenheit. This ensures
    the mobile app matches the device's built-in display.

    Type 0: Asymmetric ceiling/floor rounding based on raw value remainder
    Type 1: Standard rounding to nearest integer
    """

    ASYMMETRIC = 0  # Special rounding for remainder == 9
    STANDARD = 1  # Simple round to nearest


# ============================================================================
# Heating System Enumerations
# ============================================================================


class HeatControl(IntEnum):
    """Heating control method (for combi-boilers)."""

    UNKNOWN = 0
    SUPPLY = 1  # Control based on supply temperature
    RETURN = 2  # Control based on return temperature
    OUTSIDE_CONTROL = 3  # Outdoor temperature compensation


# ============================================================================
# Device Type Enumerations
# ============================================================================


class UnitType(IntEnum):
    """Navien device/unit model types."""

    NO_DEVICE = 0
    NPE = 1  # Tankless water heater
    NCB = 2  # Condensing boiler
    NHB = 3  # High-efficiency boiler
    CAS_NPE = 4  # Cascading NPE system
    CAS_NHB = 5  # Cascading NHB system
    NFB = 6  # Fire-tube boiler
    CAS_NFB = 7  # Cascading NFB system
    NFC = 8  # Condensing boiler
    NPN = 9  # Condensing water heater (NPN/NHW700)
    CAS_NPN = 10  # Cascading NPN system
    NPE2 = 11  # Tankless water heater (2nd gen)
    CAS_NPE2 = 12  # Cascading NPE2 system
    NCB_H = 13  # High-efficiency NCB
    NVW = 14  # Volume water heater
    CAS_NVW = 15  # Cascading NVW system
    NHB_H = 16  # High-efficiency NHB
    CAS_NHB_H = 17  # Cascading NHB-H system
    NFB_700 = 20  # Fire-tube boiler 700 series
    CAS_NFB_700 = 21  # Cascading NFB700 system
    TWC = 257  # Tankless water heater (commercial)
    NPF = 513  # Heat pump water heater


class DeviceType(IntEnum):
    """Communication device type."""

    NAVILINK = 1  # Standard NaviLink WiFi module
    NAVILINK_LIGHT = 2  # Light version NaviLink module
    NPF700_MAIN = 50  # NPF700 main controller
    NPF700_SUB = 51  # NPF700 sub-controller
    NPF700_WIFI = 52  # NPF700 WiFi module


class CommandCode(IntEnum):
    """MQTT Command codes for Navien device control.

    These command codes are used for MQTT communication with Navien devices.
    Commands are organized into two categories:

    - Query commands (16777xxx): Request device information
    - Control commands (33554xxx): Change device settings

    All commands and their expected payloads are documented in
    docs/MQTT_MESSAGES.rst under the "Control Messages" section.
    """

    # Query Commands (Information Retrieval)
    DEVICE_INFO_REQUEST = 16777217  # Request device feature information
    STATUS_REQUEST = 16777219  # Request current device status
    RESERVATION_READ = 16777222  # Read current reservation schedule
    ENERGY_USAGE_QUERY = 16777225  # Query energy usage history
    RESERVATION_MANAGEMENT = 16777226  # Update/manage reservation schedules

    # Control Commands - Power
    POWER_OFF = 33554433  # Turn device off
    POWER_ON = 33554434  # Turn device on

    # Control Commands - DHW (Domestic Hot Water) Operation
    DHW_MODE = 33554437  # Change DHW operation mode
    DHW_TEMPERATURE = 33554464  # Set DHW temperature

    # Control Commands - Scheduling
    RESERVATION_WEEKLY = 33554438  # Configure weekly temperature schedule
    TOU_RESERVATION = 33554439  # Configure Time-of-Use schedule
    RECIR_RESERVATION = 33554440  # Configure recirculation schedule
    RESERVATION_WATER_PROGRAM = 33554441  # Configure hot water program

    # Control Commands - Firmware/OTA
    OTA_COMMIT = 33554442  # Commit OTA firmware update
    OTA_CHECK = 33554443  # Check for OTA firmware updates

    # Control Commands - Recirculation
    RECIR_HOT_BTN = 33554444  # Trigger recirculation hot button
    RECIR_MODE = 33554445  # Set recirculation mode

    # Control Commands - WiFi
    WIFI_RECONNECT = 33554446  # Reconnect WiFi
    WIFI_RESET = 33554447  # Reset WiFi settings

    # Control Commands - Special Functions
    FREZ_TEMP = 33554451  # Set freeze protection temperature
    SMART_DIAGNOSTIC = 33554455  # Trigger smart diagnostics

    # Control Commands - Vacation/Away
    GOOUT_DAY = 33554466  # Set vacation mode duration (days)

    # Control Commands - Intelligent/Adaptive Mode
    RESERVATION_INTELLIGENT_OFF = 33554467  # Disable intelligent mode
    RESERVATION_INTELLIGENT_ON = 33554468  # Enable intelligent mode

    # Control Commands - Demand Response
    DR_OFF = 33554469  # Disable demand response
    DR_ON = 33554470  # Enable demand response

    # Control Commands - Anti-Legionella
    ANTI_LEGIONELLA_OFF = 33554471  # Disable anti-legionella cycle
    ANTI_LEGIONELLA_ON = 33554472  # Enable anti-legionella cycle

    # Control Commands - Air Filter (Heat Pump Models)
    AIR_FILTER_RESET = 33554473  # Reset air filter timer
    AIR_FILTER_LIFE = 33554474  # Set air filter life span

    # Control Commands - Time of Use (TOU)
    TOU_OFF = 33554475  # Disable TOU optimization
    TOU_ON = 33554476  # Enable TOU optimization


class FirmwareType(IntEnum):
    """Firmware component types."""

    UNKNOWN = 0
    CONTROLLER = 1  # Main controller firmware
    PANEL = 2  # Control panel firmware
    ROOM_CON = 3  # Room controller firmware
    COMMUNICATION_MODULE = 4  # WiFi/comm module firmware
    VALVE_CONTROL = 5  # Valve controller firmware
    SUB_ROOM_CON = 6  # Sub room controller firmware


# ============================================================================
# Display Text Helpers
# ============================================================================


DHW_OPERATION_SETTING_TEXT = {
    DhwOperationSetting.HEAT_PUMP: "Heat Pump",
    DhwOperationSetting.ELECTRIC: "Electric",
    DhwOperationSetting.ENERGY_SAVER: "Energy Saver",
    DhwOperationSetting.HIGH_DEMAND: "High Demand",
    DhwOperationSetting.VACATION: "Vacation",
    DhwOperationSetting.POWER_OFF: "Power Off",
}

CURRENT_OPERATION_MODE_TEXT = {
    CurrentOperationMode.STANDBY: "Standby",
    CurrentOperationMode.HEAT_PUMP_MODE: "Heat Pump Active",
    CurrentOperationMode.HYBRID_EFFICIENCY_MODE: "Hybrid Efficiency",
    CurrentOperationMode.HYBRID_BOOST_MODE: "Hybrid Boost",
}

HEAT_SOURCE_TEXT = {
    HeatSource.UNKNOWN: "Unknown",
    HeatSource.HEATPUMP: "Heat Pump",
    HeatSource.HEATELEMENT: "Heat Element",
    HeatSource.HEATPUMP_HEATELEMENT: "Heat Pump & Heat Element",
}

DR_EVENT_TEXT = {
    DREvent.UNKNOWN: "Not Applied",
    DREvent.RUN_NORMAL: "Run Normal",
    DREvent.SHED: "Shed",
    DREvent.LOADUP: "Load Up",
    DREvent.LOADUP_ADV: "Advance Load Up",
    DREvent.CPE: "Customer Peak Event",
}

RECIRC_MODE_TEXT = {
    RecirculationMode.UNKNOWN: "Unknown",
    RecirculationMode.ALWAYS: "Always",
    RecirculationMode.BUTTON: "Button",
    RecirculationMode.SCHEDULE: "Schedule",
    RecirculationMode.TEMPERATURE: "Temperature",
}

TOU_RATE_TEXT = {
    TouRateType.UNKNOWN: "Unknown",
    TouRateType.OFF_PEAK: "Off Peak",
    TouRateType.MID_PEAK: "Mid Peak",
    TouRateType.ON_PEAK: "On Peak",
}

FILTER_STATUS_TEXT = {
    FilterChange.NORMAL: "Normal Operation",
    FilterChange.REPLACE_NEED: "Replacement Needed",
    FilterChange.UNKNOWN: "Unknown",
}


# ============================================================================
# Error Code Enumerations
# ============================================================================


class ErrorCode(IntEnum):
    """Device error codes.

    Error codes indicate specific faults detected by the device's
    diagnostic system. Most errors are Level 1, allowing continued
    operation with reduced functionality.
    See docs/protocol/error_codes.rst for complete troubleshooting guide.
    """

    NO_ERROR = 0

    # Heating element errors
    E096_UPPER_HEATER = 96
    E097_LOWER_HEATER = 97

    # Water system errors
    E326_DRY_FIRE = 326

    # Temperature sensor errors
    E407_DHW_TEMP_SENSOR = 407
    E480_TANK_UPPER_TEMP_SENSOR = 480
    E481_TANK_LOWER_TEMP_SENSOR = 481
    E910_DISCHARGE_TEMP_SENSOR = 910
    E912_SUCTION_TEMP_SENSOR = 912
    E914_EVAPORATOR_TEMP_SENSOR = 914
    E920_AMBIENT_TEMP_SENSOR = 920

    # Mixing valve errors
    E445_MIXING_VALVE = 445

    # Relay errors
    E515_RELAY_FAULT = 515

    # System errors
    E517_DIP_SWITCH = 517
    E593_PANEL_KEY = 593
    E594_EEPROM = 594
    E595_POWER_METER = 595
    E596_WIFI = 596
    E598_RTC = 598

    # Feedback/ADC errors
    E615_FEEDBACK = 615

    # Communication errors
    E781_CTA2045 = 781

    # Valve/leak errors
    E798_SHUTOFF_VALVE = 798
    E799_WATER_LEAK = 799

    # Safety errors
    E901_ECO = 901

    # Compressor errors
    E907_COMPRESSOR_POWER = 907
    E908_COMPRESSOR = 908
    E909_EVAPORATOR_FAN = 909
    E911_DISCHARGE_TEMP_HIGH = 911
    E913_SUCTION_TEMP_LOW = 913
    E915_TEMP_DIFFERENCE = 915
    E916_EVAPORATOR_TEMP = 916

    # Refrigerant system errors
    E940_REFRIGERANT_BLOCKAGE = 940

    # Condensate errors
    E990_CONDENSATE_OVERFLOW = 990


ERROR_CODE_TEXT = {
    ErrorCode.NO_ERROR: "No Error",
    ErrorCode.E096_UPPER_HEATER: "Abnormal Upper Electric Heater",
    ErrorCode.E097_LOWER_HEATER: "Abnormal Lower Electric Heater",
    ErrorCode.E326_DRY_FIRE: "Dry Fire",
    ErrorCode.E407_DHW_TEMP_SENSOR: "Abnormal DHW Temperature Sensor",
    ErrorCode.E445_MIXING_VALVE: "Abnormal Mixing Valve",
    ErrorCode.E480_TANK_UPPER_TEMP_SENSOR: (
        "Abnormal Tank Upper Temperature Sensor"
    ),
    ErrorCode.E481_TANK_LOWER_TEMP_SENSOR: (
        "Abnormal Tank Lower Temperature Sensor"
    ),
    ErrorCode.E515_RELAY_FAULT: "Relay Fault",
    ErrorCode.E517_DIP_SWITCH: "Abnormal DIP Switch",
    ErrorCode.E593_PANEL_KEY: "Abnormal Panel Key",
    ErrorCode.E594_EEPROM: "Abnormal EEPROM",
    ErrorCode.E595_POWER_METER: "Abnormal Power Meter",
    ErrorCode.E596_WIFI: "Abnormal WiFi Connection",
    ErrorCode.E598_RTC: "Abnormal Real-Time Clock",
    ErrorCode.E615_FEEDBACK: "Abnormal Feedback",
    ErrorCode.E781_CTA2045: "Abnormal CTA-2045 Communication",
    ErrorCode.E798_SHUTOFF_VALVE: "Abnormal Shut-off Valve",
    ErrorCode.E799_WATER_LEAK: "Water Leak Detected",
    ErrorCode.E901_ECO: "Abnormal ECO Operation",
    ErrorCode.E907_COMPRESSOR_POWER: "Abnormal Compressor Power Line",
    ErrorCode.E908_COMPRESSOR: "Abnormal Compressor Operation",
    ErrorCode.E909_EVAPORATOR_FAN: "Abnormal Evaporator Fan",
    ErrorCode.E910_DISCHARGE_TEMP_SENSOR: (
        "Abnormal Discharge Temperature Sensor"
    ),
    ErrorCode.E911_DISCHARGE_TEMP_HIGH: "Abnormally High Discharge Temperature",
    ErrorCode.E912_SUCTION_TEMP_SENSOR: "Abnormal Suction Temperature Sensor",
    ErrorCode.E913_SUCTION_TEMP_LOW: "Abnormally Low Suction Temperature",
    ErrorCode.E914_EVAPORATOR_TEMP_SENSOR: (
        "Abnormal Evaporator Temperature Sensor"
    ),
    ErrorCode.E915_TEMP_DIFFERENCE: "Abnormal Temperature Difference",
    ErrorCode.E916_EVAPORATOR_TEMP: "Abnormal Evaporator Temperature",
    ErrorCode.E920_AMBIENT_TEMP_SENSOR: "Abnormal Ambient Temperature Sensor",
    ErrorCode.E940_REFRIGERANT_BLOCKAGE: "Refrigerant Line Blockage",
    ErrorCode.E990_CONDENSATE_OVERFLOW: "Condensate Overflow Detected",
}
