"""
This module defines constants for the Navien API.
"""

# MQTT Command Codes
CMD_STATUS_REQUEST = 16777219
CMD_DEVICE_INFO_REQUEST = 16777217
CMD_POWER_ON = 33554434
CMD_POWER_OFF = 33554433
CMD_DHW_MODE = 33554437
CMD_DHW_TEMPERATURE = 33554464
CMD_ENERGY_USAGE_QUERY = 16777225

# Known Firmware Versions and Field Changes
# Track firmware versions where new fields were introduced to help with debugging
KNOWN_FIRMWARE_FIELD_CHANGES = {
    # Format: "field_name": {"introduced_in": "version", "description": "what it does"}
    "heatMinOpTemperature": {
        "introduced_in": "unknown",  # First observed in production devices
        "description": "Minimum operating temperature for heating element",
        "conversion": "raw + 20",
    },
}

# Latest known firmware versions (update as new versions are discovered)
LATEST_KNOWN_FIRMWARE = {
    "controllerSwVersion": None,  # Update when firmware version is observed
    "panelSwVersion": None,
    "wifiSwVersion": None,
}
