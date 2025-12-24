# Protocol Reference

## Overview

The Navien device uses a custom binary protocol over MQTT. This document
defines the protocol values and their meanings.

## Boolean Values

The device uses non-standard boolean encoding:

| Value | Meaning | Usage | Notes |
|-------|---------|-------|-------|
| 1 | OFF / False | Power, TOU, most flags | Standard: False value |
| 2 | ON / True | Power, TOU, most flags | Standard: True value |

**Why 1 & 2?** Likely due to firmware design where:
- 0 = reserved/error
- 1 = off/false/disabled
- 2 = on/true/enabled

### Example: Device Power State
```json
{
  "power": 2  // Device is ON
}
```

When parsed via DeviceStatus: `status.power == True`

## Enum Values

### CurrentOperationMode

Used in real-time status to show what device is currently doing:

| Value | Mode | Heat Source | User Visible |
|-------|------|-------------|--------------|
| 0 | Standby | None | "Idle" |
| 32 | Heat Pump | Compressor | "Heating (HP)" |
| 64 | Energy Saver | Hybrid | "Heating (Eff)" |
| 96 | High Demand | Hybrid | "Heating (Boost)" |

Note: These are actual mode values, not sequential. The gaps (e.g., 1-31)
are reserved or correspond to error states.

### DhwOperationSetting

User-selected heating mode setting:

| Value | Mode | Efficiency | Recovery Speed |
|-------|------|------------|----------------|
| 1 | Heat Pump Only | High | Slow (8+ hrs) |
| 2 | Electric Only | Low | Fast (2-3 hrs) |
| 3 | Energy Saver | Medium | Medium (5-6 hrs) |
| 4 | High Demand | Low | Fast (3-4 hrs) |
| 5 | Vacation | None | Off |
| 6 | Power Off | None | Off |

## MQTT Topics

### Control Topic

`cmd/RTU50E-H/{deviceId}/ctrl`

Sends JSON commands to device.

### Status Topic

`cmd/RTU50E-H/{deviceId}/st`

Receives JSON status updates from device.

## Message Format

All MQTT payloads are JSON-formatted strings (not binary):

```json
{
  "header": {
    "msg_id": "1",
    "cloud_msg_type": "0x1"
  },
  "body": {
    // Message-specific fields
  }
}
```

## Common Command Codes

| Code | Command | Body Fields |
|------|---------|-------------|
| 0x11 | Set DHW Temperature | dhwSetTempH, dhwSetTempL |
| 0x21 | Set Operation Mode | dhwOperationSetting |
| 0x31 | Set Power | power |
