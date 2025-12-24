# Examples Guide

This directory contains categorized examples to help you get started with `nwp500-python`.

## Setup

Before running any example, ensure you have set your credentials:

```bash
export NAVIEN_EMAIL='your_email@example.com'
export NAVIEN_PASSWORD='your_password'
```

If using the `nwp500` library from the source code (this repository), most examples are configured to find the `src` package automatically.

## Directory Structure

*   `beginner/`: Essential scripts for basic operations. Start here.
*   `intermediate/`: Common use-cases like real-time monitoring and event handling.
*   `advanced/`: Specialized features like schedules, energy analytics, and deep diagnostics.
*   `testing/`: Scripts for testing connections and API behavior.

## Beginner Examples

Run these first to understand basic concepts.

### 01 - Authentication
`beginner/01_authentication.py`

Learn how to authenticate with Navien cloud and inspect tokens.

**Requirements:** NAVIEN_EMAIL, NAVIEN_PASSWORD env vars
**Time:** 5 minutes
**Next:** `02_list_devices.py`

### 02 - List Devices
`beginner/02_list_devices.py`

Connect to the API and list your registered devices with their basic info.

**Requirements:** Authenticated account
**Time:** 3 minutes
**Next:** `03_get_status.py`

### 03 - Get Status
`beginner/03_get_status.py`

Retrieve the real-time status (temperatures, flow rates) of a device.

**Next:** `04_set_temperature.py`

### 04 - Set Temperature
`beginner/04_set_temperature.py`

Simple control example: Setting the DHW target temperature.

## Intermediate Examples

Explore more complex interactions.

*   **`mqtt_realtime_monitoring.py`**: Subscribe to MQTT topics for real-time updates.
*   **`event_driven_control.py`**: React to events (like water usage) to trigger actions.
*   **`error_handling.py`**: Robust error handling patterns for production code.
*   **`periodic_requests.py`**: How to poll for data without overwhelming the API.
*   **`set_mode.py`**: Change device operation modes.
*   **`vacation_mode.py`**: Enable/Disable vacation mode programmatically.
*   **`command_queue.py`**: Using the command queue for reliable control.
*   **`improved_auth.py`**: Advanced authentication patterns.

## Advanced Examples

Deep dive into specific features.

*   **`device_capabilities.py`**: Inspect detailed device capabilities and flags.
*   **`mqtt_diagnostics.py`**: Low-level MQTT diagnostic tools.
*   **`auto_recovery.py`**: Implementing auto-reconnection and state recovery.
*   **`energy_analytics.py`**: Analyze energy usage reports.
*   **`tou_schedule.py`**: Configure Time-of-Use schedules.
*   **`tou_openei.py`**: Integrate with OpenEI for utility rates.
*   **`reservation_schedule.py`**: Manage heating reservation schedules.
*   **`power_control.py`**: Turn device on/off.
*   **`recirculation_control.py`**: Manage recirculation pump settings.
*   **`demand_response.py`**: Handling utility demand response signals.
*   **`token_restoration.py`**: Recovering sessions from saved tokens.

## Testing

Utilities for verifying your environment and library function.

*   **`test_api_client.py`**: Verify API connectivity and response parsing.
*   **`test_mqtt_connection.py`**: Verify MQTT broker connectivity.
*   **`test_mqtt_messaging.py`**: Test messaging reliability.
*   **`periodic_device_info.py`**: Debug tool for periodic polling.

---
**Note:** Some examples might require specific device models to function fully (e.g., recirculation control).