"""Constants and command codes for Navien device communication."""

from enum import IntEnum


class CommandCode(IntEnum):
    """
    MQTT Command codes for Navien device control.

    These command codes are used for MQTT communication with Navien devices.
    Commands are organized into two categories:

    - Query commands (16777xxx): Request device information
    - Control commands (33554xxx): Change device settings

    All commands and their expected payloads are documented in
    `docs/MQTT_MESSAGES.rst` under the "Control Messages" section.

    Examples:
        >>> CommandCode.STATUS_REQUEST
        <CommandCode.STATUS_REQUEST: 16777219>

        >>> CommandCode.POWER_ON.value
        33554434

        >>> CommandCode.POWER_ON.name
        'POWER_ON'

        >>> list(CommandCode)[:3]
        [<CommandCode.DEVICE_INFO_REQUEST: 16777217>, ...]
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
    DHW_MODE = 33554437  # Change DHW operation mode (Heat Pump/Electric/Hybrid)
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


# Note for maintainers:
# Command codes and expected payload fields are defined in
# `docs/MQTT_MESSAGES.rst` under the "Control Messages" section and
# the subsections for Power Control, DHW Mode, Anti-Legionella,
# Reservation Management and TOU Settings. When updating constants or
# payload builders, verify against that document to avoid protocol
# mismatches.

# Known Firmware Versions and Field Changes
# Track firmware versions where new fields were introduced to help with
# debugging
KNOWN_FIRMWARE_FIELD_CHANGES = {
    # Format: "field_name": {"introduced_in": "version", "description": "what it
    # does"}
    "heatMinOpTemperature": {
        "introduced_in": "Controller: 184614912, WiFi: 34013184",
        "description": "Minimum operating temperature for heating element",
        "conversion": "raw + 20",
    },
}

# Latest known firmware versions (as of 2025-10-15)
# These versions have been observed with heatMinOpTemperature field
LATEST_KNOWN_FIRMWARE = {
    "controllerSwVersion": 184614912,  # Observed on NWP500 device
    "panelSwVersion": 0,  # Panel SW version not used on this device
    "wifiSwVersion": 34013184,  # Observed on NWP500 device
}
