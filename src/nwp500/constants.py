"""Constants for Navien device communication.

Note: CommandCode has been moved to enums.py module.
Import from nwp500.enums instead of nwp500.constants.
"""

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
