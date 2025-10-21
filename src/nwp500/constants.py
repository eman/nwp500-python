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

    # Control Commands - DHW (Domestic Hot Water)
    DHW_MODE = 33554437  # Change DHW operation mode
    TOU_SETTINGS = 33554439  # Configure TOU schedule
    DHW_TEMPERATURE = 33554464  # Set DHW temperature

    # Control Commands - Anti-Legionella
    ANTI_LEGIONELLA_DISABLE = 33554471  # Disable anti-legionella cycle
    ANTI_LEGIONELLA_ENABLE = 33554472  # Enable anti-legionella cycle

    # Control Commands - Time of Use (TOU)
    TOU_DISABLE = 33554475  # Disable TOU optimization
    TOU_ENABLE = 33554476  # Enable TOU optimization


# Backward compatibility aliases
# These maintain compatibility with code using the old CMD_* naming convention
CMD_STATUS_REQUEST = CommandCode.STATUS_REQUEST
CMD_DEVICE_INFO_REQUEST = CommandCode.DEVICE_INFO_REQUEST
CMD_POWER_ON = CommandCode.POWER_ON
CMD_POWER_OFF = CommandCode.POWER_OFF
CMD_DHW_MODE = CommandCode.DHW_MODE
CMD_DHW_TEMPERATURE = CommandCode.DHW_TEMPERATURE
CMD_ENERGY_USAGE_QUERY = CommandCode.ENERGY_USAGE_QUERY
CMD_RESERVATION_MANAGEMENT = CommandCode.RESERVATION_MANAGEMENT
CMD_TOU_SETTINGS = CommandCode.TOU_SETTINGS
CMD_ANTI_LEGIONELLA_DISABLE = CommandCode.ANTI_LEGIONELLA_DISABLE
CMD_ANTI_LEGIONELLA_ENABLE = CommandCode.ANTI_LEGIONELLA_ENABLE
CMD_TOU_DISABLE = CommandCode.TOU_DISABLE
CMD_TOU_ENABLE = CommandCode.TOU_ENABLE

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
