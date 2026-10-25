Development History
===================

This document records the main implementation milestones and technical
decisions made during the development of the nwp500 Python library.

Project Overview
----------------

A Python client library for Navien NWP500 water heaters,
providing:

- REST API client for device management
- MQTT client for real-time device communication
- Event-driven architecture with automatic state change detection
- Full authentication with JWT token management
- Type-safe data models for all API responses
- Automatic reconnection with exponential backoff
- Command queuing for reliable communication
- Historical energy usage data (EMS API)
- Modern Python 3.14+ codebase with native type hints

Current Status
--------------

The library is feature-complete with:

- Complete authentication (AWS Cognito + JWT)
- REST API client (all endpoints)
- MQTT client with real-time communication
- Event emitter pattern (Phase 1 complete)
- Automatic reconnection with exponential backoff
- Command queue for disconnection handling
- Device control (power, temperature, modes)
- Real-time monitoring (status, features, energy)
- Historical energy usage data (daily breakdown)
- Thread-safe event emission from MQTT callbacks
- Documentation
- Working examples for all features
- Unit tests with good coverage
- Python 3.14+ with modern type hints

Implementation Milestones
-------------------------

Authentication Module (October 6, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented JWT-based authentication for the Navien Smart Control API:

- ``NavienAuthClient`` class with automatic token refresh
- Non-standard authorization header format (lowercase "authorization"
  without "Bearer" prefix)
- Session management with automatic credential expiration handling
- Documentation in ``AUTHENTICATION.rst``

**Files:**

- ``src/nwp500/auth.py``: core authentication module
- ``docs/AUTHENTICATION.rst``: documentation
- ``examples/authenticate.py``: basic usage example

REST API Client (October 6, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented the REST API client from the OpenAPI specification:

- All endpoints from ``/device/*`` and ``/app/*``
- Automatic authentication integration
- Type-safe data models (Device, DeviceInfo, FirmwareInfo, etc.)
- Error handling and retry logic
- Documentation in ``API_CLIENT.rst``

**Files:**

- ``src/nwp500/api_client.py``: API client implementation
- ``src/nwp500/models.py``: data models
- ``docs/API_CLIENT.rst``: documentation

MQTT Client Implementation (October 7, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented real-time MQTT communication using AWS IoT Core:

- WebSocket connection to AWS IoT endpoint
- Device-specific topic structure:
  ``cmd/{deviceType}/navilink-{deviceId}/{suffix}``
- Message publishing and subscription with callbacks
- Device control commands (power, temperature, operation mode)
- Connection lifecycle management

**Technical Decisions:**

- Used AWS IoT Device SDK for Python v2 (``awsiotsdk>=1.20.0``)
- WebSocket transport for broader network compatibility
- Automatic credential handling from authentication API
- Session ID generation for connection tracking

**Files:**

- ``src/nwp500/mqtt_client.py``: MQTT client implementation
- :doc:`../reference/python_api/mqtt_client`: documentation
- :doc:`../reference/protocol/mqtt_protocol`: message format reference

Device Status & Feature Callbacks (October 7, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Implemented typed callback system for device messages:

**Device Status (Continuous Updates):**

- ``DeviceStatus`` dataclass with 125 fields
- ``subscribe_device_status()`` method with typed callback
- Real-time monitoring of temperature, power, operation state
- Energy consumption tracking (instantaneous power, component status)

**Device Features (One-time Configuration):**

- ``DeviceFeature`` dataclass with 46 fields
- ``subscribe_device_feature()`` method with typed callback
- Firmware versions, serial numbers, capabilities
- Temperature ranges and feature flags

**Coverage:** 100% of known MQTT response types with type-safe callbacks

**Files:**

- ``src/nwp500/models.py``: DeviceStatus and DeviceFeature dataclasses
- ``docs/DEVICE_STATUS_FIELDS.rst``: field documentation
- ``examples/device_status_callback.py``: status monitoring example
- ``examples/device_feature_callback.py``: feature query example

Energy Data API (October 7, 2025)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Status:** Implemented

Energy monitoring, including historical data:

**Real-time Power Consumption (DeviceStatus):**

- ``currentInstPower`` field: Total instantaneous power (Watts)
- Component status flags: ``compUse``, ``heatUpperUse``, ``heatLowerUse``
- Available through ``subscribe_device_status()``

**Cumulative Usage (DeviceStatus):**

- ``compRunningMinuteTotal``: Total heat pump compressor runtime
- ``heater1RunningMinuteTotal``: Upper electric heater runtime
- ``heater2RunningMinuteTotal``: Lower electric heater runtime

**Energy Capacity (DeviceStatus):**

- ``availableEnergyCapacity``: energy still needed to reach the setpoint, in Watt-hours (documented as a percentage at the time, which was wrong)
- Heat pump and electric heater temperature thresholds

**Historical Energy Usage (EMS API via MQTT):**

- ``request_energy_usage()``: Query daily energy usage for specific month(s)
- ``subscribe_energy_usage()``: Subscribe to energy usage responses
- ``EnergyUsageResponse`` dataclass with daily breakdown
- ``EnergyUsageTotal`` with percentage calculations
- ``MonthlyEnergyData`` with per-day access methods
- Heat pump vs. electric element usage tracking
- Operating time statistics (hours)
- Energy consumption data (Watt-hours)
- Efficiency percentage calculations

**Files:**

- ``src/nwp500/models.py``: energy data models
- ``src/nwp500/mqtt_client.py``: energy query methods
- ``examples/energy_usage_example.py``: historical usage example
- ``docs/ENERGY_MONITORING.rst``: energy guide
- ``docs/MQTT_MESSAGES.rst``: energy query protocol

Bug Fixes & Refinements
~~~~~~~~~~~~~~~~~~~~~~~

**Topic Matching Fix (October 7):**

- Fixed regex pattern for topic subscription matching
- Added proper escaping for device ID in topic patterns
- Callbacks receive messages only for subscribed topics

**Operation Mode Clarification (October 7):**

- Documented DHW operation modes based on HAR capture analysis: Heat
  Pump Only (1), Electric Only (2), Energy Saver (3), High Demand (4)
- Additional status-only modes: Standby (0), Power Off (6)
- Fixed mode setting commands to use correct numeric values
- Added validation and examples for each mode

**Examples Updates (October 7):**

- Fixed all example scripts to use correct topic patterns
- Added error handling
- Updated to use typed callbacks where applicable
- Checked that all examples work with real devices

Testing & Verification
----------------------

All components have been tested with real Navien NWP500 devices:

**Authentication:** verified with the production API

- Sign-in flow working
- Token refresh working
- AWS credentials obtained

**REST API:** all endpoints tested

- Device listing working
- Device info retrieval working
- Firmware info working

**MQTT Client:** real-time communication verified

- WebSocket connection established
- Commands sent and acknowledged
- Status messages received and parsed
- Device control working (power, temperature, mode)

**Test Coverage:**

- Unit tests for data models
- Integration tests with real API
- Interactive examples for all features

Architecture Decisions
----------------------

Why AWS IoT Device SDK v2?
~~~~~~~~~~~~~~~~~~~~~~~~~~

The Navien API uses AWS IoT Core for MQTT messaging. The v2 SDK
provides:

- Native WebSocket support for AWS IoT
- Better async/await integration
- More reliable connection handling
- Active maintenance and security updates

Why Dataclasses for Models?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using Python dataclasses provides:

- Type safety with IDE autocomplete
- Automatic field validation
- Easy serialization/deserialization
- Documentation through type hints
- No external dependencies (stdlib only)

Why Separate Auth and API Clients?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Separation of concerns:

- Auth client can be used standalone for token management
- API client can be tested with mock tokens
- Separate responsibilities
- Easier to maintain and extend

Topic Structure Design
~~~~~~~~~~~~~~~~~~~~~~

The MQTT topic structure follows Navien's schema:

::

   cmd/{deviceType}/navilink-{deviceId}/{command}

This design:

- Namespaces commands by device type
- Allows filtering by device ID
- Supports wildcard subscriptions

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

**Features:**

- Multiple independent handlers can react to same event
- Handlers executed in priority order (higher priority = earlier execution)
- Error in one handler doesn't affect others
- Events fire only when values change
- Full backward compatibility with existing callback API
- 19 unit tests with 93% code coverage

**Files:**

- ``src/nwp500/events.py``: EventEmitter implementation (370 lines)
- ``src/nwp500/mqtt_client.py``: MQTT integration with event emitter
- ``examples/event_emitter_demo.py``: demonstration
- ``tests/test_events.py``: Unit tests (19 tests)
- :doc:`../reference/python_api/events`: Feature documentation

**Thread Safety Implementation:**


MQTT callbacks run in separate threads (e.g., 'Dummy-1') created by AWS IoT SDK. To safely emit events:

1. Event loop captured during ``connect()`` via ``asyncio.get_running_loop()``
2. ``_schedule_coroutine()`` method uses ``asyncio.run_coroutine_threadsafe()``
3. Events scheduled from any thread execute in main event loop
4. Prevents ``RuntimeError: no running event loop`` errors

Command Queue Implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Status:** Implemented

Automatic command queuing for reliable communication during network
interruptions:

- Commands sent while disconnected are automatically queued
- Queue processed in FIFO order when connection is restored
- Configurable queue size (default: 100 commands)
- Enabled by default for best user experience
- Integrates with automatic reconnection
- Properties: ``queued_commands_count`` for monitoring
- Methods: ``clear_command_queue()`` for manual management

**Files:**
- ``src/nwp500/mqtt_client.py``: Queue implementation
- ``examples/command_queue_demo.py``: demonstration
- ``tests/test_command_queue.py``: Unit tests
- ``docs/COMMAND_QUEUE.rst``: documentation

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

References
----------

- `OpenAPI Specification <openapi.yaml>`__: API specification
- :doc:`../reference/protocol/mqtt_protocol`: MQTT message reference
- :doc:`../reference/protocol/device_status`: Device status fields
- :doc:`../reference/python_api/auth_client`: Authentication guide
- :doc:`../reference/python_api/api_client`: API client guide
- :doc:`../reference/python_api/mqtt_client`: MQTT client guide
