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
CMD_RESERVATION_MANAGEMENT = 16777226
CMD_TOU_SETTINGS = 33554439
CMD_ANTI_LEGIONELLA_DISABLE = 33554471
CMD_ANTI_LEGIONELLA_ENABLE = 33554472
CMD_TOU_DISABLE = 33554475
CMD_TOU_ENABLE = 33554476

# Note for maintainers:
# These command codes and the expected payload fields are defined in
# `docs/MQTT_MESSAGES.rst` under the "Control Messages" section and
# the subsections for Power Control, DHW Mode, Anti-Legionella,
# Reservation Management and TOU Settings. When updating constants or
# payload builders, verify against that document to avoid protocol
# mismatches.

# Known Firmware Versions and Field Changes
# Track firmware versions where new fields were introduced to help with debugging
KNOWN_FIRMWARE_FIELD_CHANGES = {
    # Format: "field_name": {"introduced_in": "version", "description": "what it does"}
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
