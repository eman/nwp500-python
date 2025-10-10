Development History
===================

This document captures the key implementation milestones and technical
decisions made during the development of the nwp500 Python library.

Project Overview
----------------

A comprehensive Python client library for Navien NWP500 water heaters,
providing:

- REST API client for device management
- MQTT client for real-time device communication
- Event-driven architecture with automatic state change detection
- Full authentication with JWT token management
- Type-safe data models for all API responses
- Automatic reconnection with exponential backoff
- Command queuing for reliable communication
- Historical energy usage data (EMS API)
- Modern Python 3.9+ codebase with native type hints

Current Status
--------------

**Production Ready** ✅

The library is feature-complete with:

- ✅ Complete authentication (AWS Cognito + JWT)
- ✅ REST API client (all endpoints)
- ✅ MQTT client with real-time communication
- ✅ Event emitter pattern (Phase 1 complete)
- ✅ Automatic reconnection with exponential backoff
- ✅ Command queue for disconnection handling
- ✅ Device control (power, temperature, modes)
- ✅ Real-time monitoring (status, features, energy)
- ✅ Historical energy usage data (daily breakdown)
- ✅ Thread-safe event emission from MQTT callbacks
- ✅ Comprehensive documentation
- ✅ Working examples for all features
- ✅ Unit tests with good coverage
- ✅ Python 3.9+ with modern type hints

Implementation Milestones
-------------------------

Authentication Module (October 6, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented complete JWT-based authentication for the Navien Smart
Control API: - ``NavienAuthClient`` class with automatic token refresh -
Non-standard authorization header format (lowercase “authorization”
without “Bearer” prefix) - Session management with automatic credential
expiration handling - Comprehensive documentation in
``AUTHENTICATION.rst``

**Key Files:** - ``src/nwp500/auth.py`` - Core authentication module -
``docs/AUTHENTICATION.rst`` - Complete documentation -
``examples/authenticate.py`` - Basic usage example

REST API Client (October 6, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented full REST API client based on OpenAPI specification: - All
endpoints from ``/device/*`` and ``/app/*`` - Automatic authentication
integration - Type-safe data models (Device, DeviceInfo, FirmwareInfo,
etc.) - Error handling and retry logic - Comprehensive documentation in
``API_CLIENT.rst``

**Key Files:** - ``src/nwp500/api_client.py`` - API client
implementation - ``src/nwp500/models.py`` - Data models -
``docs/API_CLIENT.rst`` - Complete documentation

MQTT Client Implementation (October 7, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented real-time MQTT communication using AWS IoT Core: - WebSocket
connection to AWS IoT endpoint - Device-specific topic structure:
``cmd/{deviceType}/navilink-{deviceId}/{suffix}`` - Message publishing
and subscription with callbacks - Device control commands (power,
temperature, operation mode) - Connection lifecycle management

**Key Technical Decisions:** - Used AWS IoT Device SDK for Python v2
(``awsiotsdk>=1.20.0``) - WebSocket transport for broader network
compatibility - Automatic credential handling from authentication API -
Session ID generation for connection tracking

**Key Files:** - ``src/nwp500/mqtt_client.py`` - MQTT client
implementation - :doc:`MQTT_CLIENT` - Complete documentation -
:doc:`MQTT_MESSAGES` - Message format reference

Device Status & Feature Callbacks (October 7, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented typed callback system for device messages:

**Device Status (Continuous Updates):** - ``DeviceStatus`` dataclass
with 125 fields - ``subscribe_device_status()`` method with typed
callback - Real-time monitoring of temperature, power, operation state -
Energy consumption tracking (instantaneous power, component status)

**Device Features (One-time Configuration):** - ``DeviceFeature``
dataclass with 46 fields - ``subscribe_device_feature()`` method with
typed callback - Firmware versions, serial numbers, capabilities -
Temperature ranges and feature flags

**Coverage:** 100% of known MQTT response types with type-safe callbacks

**Key Files:** - ``src/nwp500/models.py`` - DeviceStatus and
DeviceFeature dataclasses - ``docs/DEVICE_STATUS_FIELDS.rst`` - Field
documentation - ``examples/device_status_callback.py`` - Status
monitoring example - ``examples/device_feature_callback.py`` - Feature
query example

Energy Data API (October 7, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Status:** ✅ Implemented

Complete energy monitoring capabilities including historical data:

**Real-time Power Consumption (DeviceStatus):**
- ``currentInstPower`` field: Total instantaneous power (Watts)
- Component status flags: ``compUse``, ``heatUpperUse``, ``heatLowerUse``
- Available through ``subscribe_device_status()``

**Cumulative Usage (DeviceStatus):**
- ``compRunningMinuteTotal``: Total heat pump compressor runtime
- ``heater1RunningMinuteTotal``: Upper electric heater runtime
- ``heater2RunningMinuteTotal``: Lower electric heater runtime

**Energy Capacity (DeviceStatus):**
- ``availableEnergyCapacity``: Available energy percentage (0-100%)
- Heat pump and electric heater temperature thresholds

**Historical Energy Usage (EMS API via MQTT):**
- ``request_energy_usage()`` - Query daily energy usage for specific month(s)
- ``subscribe_energy_usage()`` - Subscribe to energy usage responses
- ``EnergyUsageResponse`` dataclass with daily breakdown
- ``EnergyUsageTotal`` with percentage calculations
- ``MonthlyEnergyData`` with per-day access methods
- Heat pump vs. electric element usage tracking
- Operating time statistics (hours)
- Energy consumption data (Watt-hours)
- Efficiency percentage calculations

**Key Files:**
- ``src/nwp500/models.py`` - Energy data models
- ``src/nwp500/mqtt_client.py`` - Energy query methods
- ``examples/energy_usage_example.py`` - Historical usage example
- ``docs/ENERGY_MONITORING.rst`` - Complete energy guide
- ``docs/MQTT_MESSAGES.rst`` - Energy query protocol

Bug Fixes & Refinements
~~~~~~~~~~~~~~~~~~~~~~~

**Topic Matching Fix (October 7):** - Fixed regex pattern for topic
subscription matching - Added proper escaping for device ID in topic
patterns - Ensured callbacks receive messages only for subscribed topics

**Operation Mode Clarification (October 7):** - Documented DHW operation
modes based on HAR capture analysis: Heat Pump Only (1), Electric Only
(2), Energy Saver (3), High Demand (4) - Additional status-only modes:
Standby (0), Power Off (6) - Fixed mode setting commands to use correct
numeric values - Added validation and examples for each mode

**Examples Updates (October 7):** - Fixed all example scripts to use
correct topic patterns - Added comprehensive error handling - Updated to
use typed callbacks where applicable - Ensured all examples work with
real devices

Testing & Verification
----------------------

All components have been tested with real Navien NWP500 devices:

**Authentication:** ✅ Verified with production API - Sign-in flow
working - Token refresh working - AWS credentials properly obtained

**REST API:** ✅ All endpoints tested - Device listing working - Device
info retrieval working - Firmware info working

**MQTT Client:** ✅ Real-time communication verified - WebSocket
connection established - Commands sent and acknowledged - Status
messages received and parsed - Device control working (power,
temperature, mode)

**Test Coverage:** ✅ Comprehensive - Unit tests for data models -
Integration tests with real API - Interactive examples for all features

Architecture Decisions
----------------------

Why AWS IoT Device SDK v2?
~~~~~~~~~~~~~~~~~~~~~~~~~~

The Navien API uses AWS IoT Core for MQTT messaging. The v2 SDK
provides: - Native WebSocket support for AWS IoT - Better async/await
integration - More reliable connection handling - Active maintenance and
security updates

Why Dataclasses for Models?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using Python dataclasses provides: - Type safety with IDE autocomplete -
Automatic field validation - Easy serialization/deserialization - Clear
documentation through type hints - No external dependencies (stdlib
only)

Why Separate Auth and API Clients?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Separation of concerns: - Auth client can be used standalone for token
management - API client can be tested with mock tokens - Clear
responsibility boundaries - Easier to maintain and extend

Topic Structure Design
~~~~~~~~~~~~~~~~~~~~~~

The MQTT topic structure follows Navien’s schema:

::

   cmd/{deviceType}/navilink-{deviceId}/{command}

This design: - Namespaces commands by device type - Allows filtering by
device ID - Supports wildcard subscriptions for flexibility - Maintains
compatibility with Navien mobile app

Recent Enhancements (2025)
--------------------------

Event Emitter Pattern (Phase 1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Status:** Implemented (October 2025)

Complete event-driven architecture for device state changes:

- **EventEmitter Base Class**: Multiple listeners per event with priority-based execution
- **Async Support**: Native support for both sync and async event handlers
- **One-Time Listeners**: ``once()`` method for handlers that auto-remove after execution
- **Dynamic Management**: ``on()``, ``off()``, ``remove_all_listeners()`` methods
- **Event Statistics**: ``listener_count()``, ``event_count()``, ``event_names()`` methods
- **Wait Pattern**: ``wait_for()`` method to wait for specific events with timeout
- **Thread Safety**: Safe event emission from MQTT callback threads via ``_schedule_coroutine()``
- **State Change Detection**: Automatic detection and emission of state changes

**Events Emitted (11 total):**

- Status Events: ``status_received``, ``temperature_changed``, ``mode_changed``, ``power_changed``, ``heating_started``, ``heating_stopped``, ``error_detected``, ``error_cleared``
- Connection Events: ``connection_interrupted``, ``connection_resumed``
- Feature Events: ``feature_received``

**Key Features:**

- Multiple independent handlers can react to same event
- Handlers executed in priority order (higher priority = earlier execution)
- Error in one handler doesn't affect others
- Events only fire when values actually change
- Full backward compatibility with existing callback API
- 19 unit tests with 93% code coverage

**Key Files:**

- ``src/nwp500/events.py`` - EventEmitter implementation (370 lines)
- ``src/nwp500/mqtt_client.py`` - MQTT integration with event emitter
- ``examples/event_emitter_demo.py`` - Comprehensive demonstration
- ``tests/test_events.py`` - Unit tests (19 tests)
- :doc:`EVENT_EMITTER` - Feature documentation

**Thread Safety Implementation:**

MQTT callbacks run in separate threads (e.g., 'Dummy-1') created by AWS IoT SDK. To safely emit events:

1. Event loop captured during ``connect()`` via ``asyncio.get_running_loop()``
2. ``_schedule_coroutine()`` method uses ``asyncio.run_coroutine_threadsafe()``
3. Events scheduled from any thread execute in main event loop
4. Prevents ``RuntimeError: no running event loop`` errors

Command Queue Implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Status:** ✅ Implemented

Automatic command queuing for reliable communication during network
interruptions:

- Commands sent while disconnected are automatically queued
- Queue processed in FIFO order when connection is restored
- Configurable queue size (default: 100 commands)
- Enabled by default for best user experience
- Integrates seamlessly with automatic reconnection
- Properties: ``queued_commands_count`` for monitoring
- Methods: ``clear_command_queue()`` for manual management

**Key Files:**
- ``src/nwp500/mqtt_client.py`` - Queue implementation
- ``examples/command_queue_demo.py`` - Complete demonstration
- ``tests/test_command_queue.py`` - Unit tests
- ``docs/COMMAND_QUEUE.rst`` - Comprehensive documentation

Python 3.9+ Migration
~~~~~~~~~~~~~~~~~~~~~

**Status:** Completed

Modernized codebase to use Python 3.9+ native type hints (PEP 585):

- Minimum Python version: 3.9+ (was 3.8)
- Native type hints: ``dict[str, Any]`` instead of ``Dict[str, Any]``
- Removed ``typing.Dict``, ``typing.List``, ``typing.Deque`` imports
- Cleaner, more readable code
- Better IDE support
- Aligned with modern Python standards

**Impact:**
- All type hints updated throughout codebase
- setup.cfg updated with python_requires = >=3.9
- Python version classifiers added (3.9-3.13)
- ruff target-version updated to py39

Future Enhancements
-------------------

Potential areas for future development:

1. **Event System Phase 2:** Event filtering with lambda conditions, event middleware, event buffering and replay
2. **Event System Phase 3:** Event namespacing with wildcards (``device.*``), event history and time-travel debugging, performance metrics and monitoring
3. **Multiple Devices:** Efficient handling of multiple simultaneous device connections
4. **Configuration Validation:** Validate settings against device capabilities
5. **Command Priority Queue:** Different priority levels for different command types
6. **Queue Persistence:** Save queue to disk for recovery after restart

References
----------

- `OpenAPI Specification <openapi.yaml>`__ - API specification
- :doc:`MQTT_MESSAGES` - MQTT message reference
- :doc:`DEVICE_STATUS_FIELDS` - Device status fields
- :doc:`AUTHENTICATION` - Authentication guide
- :doc:`API_CLIENT` - API client guide
- :doc:`MQTT_CLIENT` - MQTT client guide
